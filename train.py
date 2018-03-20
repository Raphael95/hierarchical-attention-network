import json
import shutil
import time
import torch
import numpy as np
from tensorboardX import SummaryWriter
from torch.autograd import Variable
from sklearn.metrics import confusion_matrix, f1_score
from IPython.core.debugger import Pdb


def train(model, dataloader, criterion, optimizer, use_gpu=False):
    model.train()  # Set model to training mode
    running_loss = 0.0
    running_corrects = 0
    example_count = 0
    # Pdb().set_trace()
    running_targets = np.empty(len(dataloader.dataset.targets), dtype=int)
    running_preds = np.empty(len(dataloader.dataset.targets), dtype=int)
    step = 0
    # Iterate over data.
    for documents, targets in dataloader:
        if use_gpu:
            targets = targets.cuda()
        targets = Variable(targets, requires_grad=False)

        # zero grad
        optimizer.zero_grad()
        # Pdb().set_trace()
        scores = model(documents)
        _, preds = torch.max(scores, 1)
        loss = criterion(scores, targets)

        # backward + optimize
        loss.backward()
        for p in model.parameters():
            if p.grad is None:
                continue
            p.grad.data.clamp_(-0.25, 0.25)
        optimizer.step()

        # statistics
        running_loss += loss.data[0]
        running_corrects += torch.sum((preds == targets).data)
        running_targets[example_count:example_count + targets.size(0)] = targets.data.cpu().numpy()
        running_preds[example_count:example_count + targets.size(0)] = preds.data.cpu().numpy()
        example_count += targets.size(0)
        step += 1
        if step % 100 == 0:
            print('running loss: {}, running_corrects: {}, example_count: {}, acc: {}'.format(
                running_loss / example_count, running_corrects, example_count, (float(running_corrects) / example_count) * 100))
            print(confusion_matrix(running_targets[:example_count], running_preds[:example_count], labels=[0, 1, 2]))
            print("macro-F1={:4.4f}".format(f1_score(running_targets[:example_count], running_preds[:example_count], labels=[0, 1, 2], average='macro')))
        if example_count + dataloader.batch_size > len(dataloader.dataset.targets):
            break
    loss = running_loss / example_count
    acc = (running_corrects / len(dataloader.dataset)) * 100
    print('Train Loss: {:.4f} Acc: {:2.3f} ({}/{})'.format(loss,
                                                           acc, running_corrects, example_count))
    return loss, acc


def validate(model, dataloader, criterion, use_gpu=False):
    model.eval()  # Set model to evaluate mode
    running_loss = 0.0
    running_corrects = 0
    example_count = 0
    # Iterate over data.
    for documents, targets in dataloader:
        if use_gpu:
            targets = targets.cuda()
        targets = Variable(targets)

        # zero grad
        scores = model(documents)
        _, preds = torch.max(scores, 1)
        loss = criterion(scores, targets)

        # statistics
        running_loss += loss.data[0]
        running_corrects += torch.sum((preds == targets).data)
        example_count += targets.size(0)
    loss = running_loss / example_count
    # acc = (running_corrects / example_count) * 100
    acc = (running_corrects / len(dataloader.dataset)) * 100
    print('Validation Loss: {:.4f} Acc: {:2.3f} ({}/{})'.format(loss,
                                                                acc, running_corrects, example_count))
    return loss, acc


def train_model(model, data_loaders, criterion, optimizer, scheduler, save_dir, num_epochs=25, use_gpu=False, best_accuracy=0, start_epoch=0):
    print('Training Model with use_gpu={}...'.format(use_gpu))
    since = time.time()

    best_model_wts = model.state_dict()
    best_acc = best_accuracy
    writer = SummaryWriter(save_dir)
    for epoch in range(start_epoch, num_epochs):
        print('Epoch {}/{}'.format(epoch, num_epochs - 1))
        print('-' * 10)
        train_begin = time.time()
        train_loss, train_acc = train(
            model, data_loaders['train'], criterion, optimizer, use_gpu)
        train_time = time.time() - train_begin
        print('Epoch Train Time: {:.0f}m {:.0f}s'.format(
            train_time // 60, train_time % 60))
        writer.add_scalar('Train Loss', train_loss, epoch)
        writer.add_scalar('Train Accuracy', train_acc, epoch)

        validation_begin = time.time()
        val_loss, val_acc = validate(
            model, data_loaders['val'], criterion, use_gpu)
        validation_time = time.time() - validation_begin
        print('Epoch Validation Time: {:.0f}m {:.0f}s'.format(
            validation_time // 60, validation_time % 60))
        writer.add_scalar('Validation Loss', val_loss, epoch)
        writer.add_scalar('Validation Accuracy', val_acc, epoch)

        # deep copy the model
        is_best = val_acc > best_acc
        if is_best:
            best_acc = val_acc
            best_model_wts = model.state_dict()

        save_checkpoint(save_dir, {
            'epoch': epoch,
            'best_acc': best_acc,
            'state_dict': model.state_dict(),
            # 'optimizer': optimizer.state_dict(),
        }, is_best)

        writer.export_scalars_to_json(save_dir + "/all_scalars.json")
        valid_error = 1.0 - val_acc / 100.0
        if type(scheduler) == CustomReduceLROnPlateau:
            scheduler.step(valid_error, epoch=epoch)
            if scheduler.shouldStopTraining():
                print("Stop training as no improvement in accuracy - no of unconstrainedBadEopchs: {0} > {1}".format(
                    scheduler.unconstrainedBadEpochs, scheduler.maxPatienceToStopTraining))
                # Pdb().set_trace()
                break
        else:
            scheduler.step()

    time_elapsed = time.time() - since
    print('Training complete in {:.0f}m {:.0f}s'.format(
        time_elapsed // 60, time_elapsed % 60))
    print('Best val Acc: {:4f}'.format(best_acc))
    # load best model weights
    model.load_state_dict(best_model_wts)

    # export scalar data to JSON for external processing
    writer.export_scalars_to_json(save_dir + "/all_scalars.json")
    writer.close()

    return model


def save_checkpoint(save_dir, state, is_best):
    savepath = save_dir + '/' + 'checkpoint.pth.tar'
    torch.save(state, savepath)
    if is_best:
        shutil.copyfile(savepath, save_dir + '/' + 'model_best.pth.tar')


def test_model(model, dataloader, itoa, outputfile, use_gpu=False):
    model.eval()  # Set model to evaluate mode
    running_corrects = 0
    example_count = 0
    test_begin = time.time()
    outputs = []

    # Iterate over data.
    for documents, targets in dataloader:
        if use_gpu:
            targets = targets.cuda()
        targets = Variable(targets)

        scores = model(documents)
        _, preds = torch.max(scores, 1)

        if example_count % 100 == 0:
            print('(Example Count: {})'.format(example_count))
        # statistics
        running_corrects += torch.sum((preds == targets).data)
        example_count += targets.size(0)

    json.dump(outputs, open(outputfile, 'w'))
    print('(Example Count: {})'.format(example_count))
    test_time = time.time() - test_begin
    acc = (running_corrects / len(dataloader.dataset)) * 100
    print('Acc: {:2.3f} ({}/{})'.format(acc, running_corrects, example_count))
    print('Test Time: {:.0f}m {:.0f}s'.format(test_time // 60, test_time % 60))